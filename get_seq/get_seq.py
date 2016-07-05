from __future__ import division, print_function
import os, sys,re, click, requests, bs4, json
from pyensembl import EnsemblRelease
from useful_tools.transcription_translation import transcription, translation
from useful_tools.output import write_to_output
from useful_tools import useful


class WrongHGversion(Exception):
    pass

class TypographyError(Exception):
    pass
    
class ErrorUCSC(Exception):
    pass

file_path = useful.cwd_file_path(__file__)
   
@click.command('main')
@click.argument('input_file',nargs=1, required=False)
@click.option('--output_file',default=None, help='give an output file, requires input to be a file')
@click.option('--upstream', default=20, help="number of bases to get upstream, default: 20") # default to an int makes option accept int only
@click.option('--downstream',default=20, help="number of bases to get downstream, default: 20")
@click.option('--hg_version',default="hg19", help="human genome version. default: hg19")
@click.option('--header/--no_header',default='n',help="header gives metadata i.e. sequence name etc.")
@click.option('--transcribe/--nr',default='n',help="transcribe into RNA sequence")
@click.option('--translate/--np',default='n',help="translate RNA seq into protein seq")
@click.option('--rc/--no_rc',default='n',help="reverse complement the DNA")
@click.option('--seq_file', default=None, help="match sequence with .seq file contents")
@click.option('--seq_dir', default=file_path+"seq_files/")

# what use is there in just transcribing and translating for the sake of it? perhaps use an intiation codon finder which can be used o run through a DNA sequence pior to transcripion and transcribing from said site. Also something which checks the dna seq is a multiple of 3 would also be useful. Perhaps something where I could push the rna/protein seq to find which gene exon etc. is or maybe nBLAST, pBLAST etc which I am sure BioPython will have something for parsing to.

def main(input_file, output_file=None, upstream=20, downstream=20, hg_version="hg19",
          header="n", transcribe="n", translate="n",
            rc='n', seq_file=None, seq_dir=file_path+"seq_files/"):
        '''
    Produce a sequence using the UCSC DAS server from an inputted genomic 
	postion and defined number of bases upstream and downstream from said 
	position. A genomic range can be used in place of a genomic position
	and renders the upstream/downstream options irrelevant. An input file
	can have a mixture of genomic positions and genomic ranges. genomic
    ranges is not compatible with the --seq_file option.
         \b\n
    A file or string can be used as input. STRING: either a variant position 
    or a genomic range deliminated by a comma. FILE: deliminated file with 
    the variant name and the variant position
         \b\n
    Example:\b\n
        get_seq chr1:169314424 --dash --upstream 200 --downstream 200\n
        get_seq chr1:169314424,169314600 --hg_version hg38\n
        get_seq input.txt --output_file output.txt --header\n
        ''' 
        # allows one to pipe in an argument at the cmd
        if not input_file:
            input_file = input()
        
        # parse arguments into the ScrapeSeq and ProteinRNA Class 
        reference = ScrapeSeq(input_file, output_file, upstream,
                              downstream, hg_version, header)
        trans = ProteinRNA(transcribe, translate, rc)
        
        # get the path to this file
        
        # if the arg given is a file, parse it in line by line
        if os.path.isfile(input_file) is True:
            all_scrapped_info = []
            if seq_file:
                print("\nWARNING:--seq_file argument ignored. Automatically" 
                      +" searching seq_files directory for a matching file\n")
            for line in [line.rstrip("\n").split("\t") for line in open(input_file)]:
                seq_name = line[0]
                var_pos = line[1]
                ensembl = ScrapeEnsembl(var_pos, hg_version)
                seq_file = CompareSeqs.get_matching_seq_file(seq_name, seq_dir)
                sanger = CompareSeqs(upstream, downstream, seq_file)
                sequence_info = get_seq(seq_name, var_pos, reference, trans, 
                                        sanger, ensembl)
                all_scrapped_info.append(sequence_info)

        else:
            ensembl = ScrapeEnsembl(input_file, hg_version)
            sanger = CompareSeqs(upstream,downstream, seq_file)
            get_seq("query", input_file, reference, trans, sanger, ensembl)

        if output_file:
            header = "\t".join(("Name", "Position", "Seq Range", "Gene Name", 
                                "Gene ID", "Type", "Gene Range", "Transcript",
                                "Exon ID", "Intron", "Exon", "Ref", "Seq", "Result",
                                "\n"))
            write_to_output(all_scrapped_info, output_file, header)




        

def get_seq(seq_name, var_pos, reference, trans, sanger, ensembl):
        # adds all scrapped data to a list, which is written to an output file if the 
        # option is selected
        try:
            # check each individual line of the file for CUSTOM ERRORS
            error_check = reference.handle_argument_exception(var_pos)
            
            # check if var_pos is a GENOMIC REGION, else construct one from var_pos
            seq_range = reference.create_region(var_pos)
            
            # use UCSC to get the genomic ranges DNA sequence
            sequence = reference.get_region_info(seq_range)
            
            # assess whether the var pos base in the sanger trace (seq_file) is
            # different to the reference base 
            sanger_sequence = sanger.match_with_seq_file(sequence)
            if isinstance(sanger_sequence, tuple):# if sanger_sequence is tuple else
                ref_base = sanger_sequence[1] 
                sanger_base = sanger_sequence[2] 

                # compare the reqerence var_pos base and the sanger var_pos base
                compare = CompareSeqs.compare_nucleotides(ref_base,sanger_base) 
            
            # detrmine whether to transcribe or translate to RNA or PROTEIN
            sequence = str(trans.get_rna_seq(sequence))
            sequence = str(trans.get_protein_seq(sequence))

            # determine whether to give a HEADER
            header = reference.header_option(seq_name,var_pos,
                                           seq_range,sequence)
            
            # get gene information for the variant position
            gene_info = ensembl.get_gene_info()
            if gene_info:
                gene_name, gene_id, gene_type, gene_range = gene_info
                transcript = ensembl.get_canonical_transcript(gene_name)
                exon_info = get_exon_numbers(seq_name, transcript, var_pos, ensembl)
                exon_id, intron, exon = exon_info

            

            if isinstance(sanger_sequence, tuple) and gene_info:
                print("\n".join((header,"Reference Sequence:\t"+sequence,
                                 "Sanger Sequence:\t"+sanger_sequence[0],
                                 compare[0],"\n")))
                return("\t".join((seq_name, var_pos, seq_range, gene_name,
                                  gene_id, gene_type, gene_range, transcript, 
                                  exon_id, intron, exon, ref_base,
                                  sanger_base, str(compare[1]))))

            elif not gene_info and isinstance(sanger_sequence, tuple):
                print("\n".join((header, "Reference Sequence:\t"+sequence,
                                 "Sanger Sequence:\t"+sanger_sequence[0],
                                 compare[0], "\n")))
            elif not gene_info:
                print("\n".join((header, "Reference Sequence:\t"+sequence,"\n")))

            else:
                print("\n".join((header,"Reference Sequence:\t"+sequence, "\n")))
                return("\t".join((seq_name, var_pos, seq_range, gene_name, gene_id,  
                                  gene_type, gene_range, "-", "-",str(0))))


        except WrongHGversion:
            print("Human genome version "+hg_version+" not recognised")
            sys.exit(0)
        except TypographyError:
            print("Only one colon and no more than one comma/dash is allowed for "
                  +var_pos+" in "+seq_name+"\n")    
        except ErrorUCSC:
            print(var_pos+" in "+seq_name+" is not recognised by UCSC"+"\n")


def get_exon_numbers(name, transcript, pos, ensembl):

    exon_dics = ensembl.request_ensembl(transcript)
    exon_region = ensembl.all_exon_regions(exon_dics,transcript)
    exon_id = ensembl.get_exon_id(exon_region,pos) # filter for exon id in which variant is within
    if not exon_id:
        sorted_exon_regions = sorted(exon_region)
        intron_region = ensembl.all_intron_regions(sorted_exon_regions)
        intron_num = ensembl.intron_number(intron_region,pos)
        
        if intron_num is None:
            return (pos,transcript,"NO INTRON/EXON MATCHED")
        else:
            last_exon = ensembl.total_exons(exon_dics,transcript)
            last_intron = int(last_exon)-1
            return ("Intron",str(intron_num)+"/"+str(last_intron),"-")
    else:
        exon_num = ensembl.exon_number(exon_dics,exon_id,transcript)    # use th exon_id to get exon number
        last_exon = ensembl.total_exons(exon_dics,transcript)           # get total exons of transcript
        
        
        return (exon_id[0], "-" ,str(exon_num)+"/"+str(last_exon))

   

      


class ScrapeEnsembl():
    ''' Let me become a SUPEER CLASS!
    '''
    def __init__(self, query, hg_version):
        self.query = query
        self.hg_version = ScrapeEnsembl.genome.get(hg_version) # convert to ensembl release
        self.hg = EnsemblRelease(self.hg_version) # convert to ensembl release object


    genome = {"hg19": 75, "hg38": 83}
    
    def get_gene_info(self):
        ''' take input and transform into genomic position or range
        '''
        
        # check if the input is a genomic position or genomic range
        if re.search(r"[-:]", self.query) and self.query.replace(":","").isdigit() or self.query.startswith("X"):
            chrom = self.query.split(":")[0]
            pos = int(self.query.split(":")[1])
            gene_name = self.hg.gene_names_at_locus(contig=chrom, position=pos)
            if gene_name:
                gene_info = self.hg.genes_by_name(gene_name[0])
                # not sure how to manipulate Gene() object correctly so splitting will do
                # and reorganise as a tuple
                gene_info_split = re.split(r"[=,]",str(gene_info[0]))
                gene_id = gene_info_split[1]
                gene_type = gene_info_split[5]
                gene_range = gene_info_split[7][:-1]

                gene_info = (gene_name[0], gene_id, gene_type, gene_range)
            
                return(gene_info)
    
    
    def get_canonical_transcript(self, gene_name):
        ''' Determine and return the canonical transcript of the given gene
        '''
        all_transcripts = self.hg.transcript_ids_of_gene_name(gene_name)
        all_transcript_details = [self.hg.transcript_by_id(x) for x in all_transcripts]
        protein_coding_transcripts = []
        for x in all_transcript_details:
            split_transcript_info = re.split(r"[=,]",str(x))
            transcript = split_transcript_info[1]
            transcript_type = split_transcript_info[9]
            location = split_transcript_info[-1][:-1]
            start = re.split(r"[:-]", location)[1]
            stop = re.split(r"[:-]", location)[2]
            size = int(stop) - int(start)
            if transcript_type == "protein_coding":
                protein_coding_transcripts.append((size,transcript,transcript_type)) 

        # sort by size and return the largest protein coding transcript
        canonical_transcript = sorted(protein_coding_transcripts)[-1][1]
        return canonical_transcript

    
    def request_ensembl(self,transcript):
        ''' Retrieve all expanded exon information associated with a given transcript ID
            in JSON format
        '''
        try:
            if self.hg_version == 75:
                grch = "grch37."
            elif self.hg_version > 80:
                grch = "."
            else:
                print("incompatible human genome version")
            
            url = "".join(("http://",grch,"rest.ensembl.org/overlap/id/",transcript,
                           "?feature=exon;content-type=application/json;expand=1"))
            req = requests.get(url)
            req.raise_for_status()
            exon_dics = req.json()
            return exon_dics
        except requests.exceptions.RequestException as e:
            return e


    def all_exon_regions(self, exon_dics, transcript):
        '''Get every exon ID and its start and stop position which resides within the
           given transcript
        '''
        exon_region = set()
        for exon_dicts in exon_dics:
            if exon_dicts.get("Parent") == transcript:
                rank = exon_dicts.get("rank")
                start = exon_dicts.get("start")
                end = exon_dicts.get("end")
                exon = exon_dicts.get("exon_id")
                exon_start_end = (rank, exon, start, end)
                exon_region.add(exon_start_end)

        return exon_region
       

    def all_intron_regions(self,sorted_exon_regions):
        ''' Get all intron numbers, start and stop positions
        ''' 
        intron_region = set()
        
        for i in range(0,len(sorted_exon_regions)):
            for x in range(0,len(sorted_exon_regions)):
                if x == i +1:
                    intron_number = str(sorted_exon_regions[i][0])
                    end_pos_previous_exon = str(sorted_exon_regions[i][3])
                    start_pos_next_exon = str(sorted_exon_regions[x][2])
                    intron_info = (int(intron_number),end_pos_previous_exon,\
                    start_pos_next_exon,str(int(end_pos_previous_exon)-
                                            int(start_pos_next_exon)))
                    intron_region.add(intron_info)
        
        return intron_region


    def intron_number(self,intron_region,pos):
        ''' Returns the intron number in which the variant is within
        '''
        
        for intron in intron_region:
            if int(intron[3]) > 0:
             # no idea why the start and end pos are swapped, hence the need for if/else
                for x in range(int(intron[2]),int(intron[1])):          
                    if x == int(pos.split(":")[1]):
                        intron_num= intron[0]
                        return intron_num
            else:
                for x in range(int(intron[1]),int(intron[2])):
                    if x == int(pos.split(":")[1]):
                        intron_num= intron[0]
                        return intron_num  

                            
    def get_exon_id(self,exon_region,pos):  
        ''' Get the exon id for which the variant position is within.
        
            Use the exon_region tuple to iterate between the start and stop 
            positions of each exon within the transcript until one number 
            matches the variant position number, then return the exon_id 
            associated with that position.
        '''  
        exon_id = []      
        for exons in sorted(exon_region):
            for x in range(exons[2],exons[3]):
                if x == int(pos.split(":")[1]):
                    exon_id.append(exons[1])
        
        return exon_id
        



    def exon_number(self,exon_dics,exon_id,transcript):
        ''' Returns the exon number in which the variant is within.
        
            use the exon_id to retrieve the matching dictionary and extract
            the rank (exon number) from that dictionary.
        '''
        for y in exon_dics:
            if y.get("exon_id") == exon_id[0] and y.get("Parent") == transcript:
                exon_number = y.get("rank")
       
        return exon_number

            
        
    def total_exons(self,exon_dics,transcript):
        ''' Get the last exon number in the transcript
        
            List comprehension which extracts all exon numbers found in all the 
            dictionarys with the transcript id. Extract and return the last element
            as the total_exons in the generated list.
        '''
        all_exon_ranks = [i.get("rank") for i in exon_dics 
                          if i.get("Parent") == transcript]
        total_exons = all_exon_ranks[-1]
        return total_exons

   
    
        
        
            



class ScrapeSeq():

    def __init__(self,input_file,output_file,upstream, downstream, hg_version, 
                 header):
        
        self.input_file = input_file
        self.output_file = output_file
        self.upstream = upstream
        self.downstream = downstream
        self.hg_version = hg_version
        self.header = header

                 
    def handle_argument_exception(self,var_pos):
        ''' Stores custom exceptions
        '''        
        
        if self.hg_version not in ["hg16","hg17","hg18","hg19","hg38"]:
            raise WrongHGversion("Human genome version "+self.hg_version+
                                 " not recognised")
            sys.exit(0)
            
        
        if var_pos.count(",") > 1 or var_pos.count("-") >1:
            raise TypographyError("too many commas in "+self.input_file)
            
            
        if var_pos.count(":") < 1 or var_pos.count(":") >1:
            raise TypographyError("A single colon is required to seperate"+\
                                  "the chromosome and position numbers in the"+\
                                  "variant position: "+self.input_file)
                                             
                
    def create_region(self,var_pos):
        ''' use the variant position given, add and subtract the 
            numbers given in upstream and downstream respectively
            from the given variant position to return a genomic range.
        '''
        # check if var_pos is a GENOMIC REGION, else construct one from var_pos
        if re.search(r"[,-]",var_pos):
            var_pos = var_pos.replace("-",",")
            return var_pos

        else:                    
            nospace = var_pos.replace(" ","")
            chrom = nospace.split(":")[0]
            pos = nospace.split(":")[1]
            start_pos = int(pos) - self.upstream
            end_pos = int(pos) + self.downstream
            seq_range = chrom+":"+str(start_pos)+","+str(end_pos)
            return seq_range
                
                
    def get_region_info(self, seq_range):
        ''' From a genomic range and human genome version, use UCSC DAS server
            to retrieve the sequence found in the given genomic range.

            http://www.biodas.org/documents/spec-1.53.html
        '''
        # scrape for the sequence associated with the seq_range AKA genomic region 
        req = requests.get("http://genome.ucsc.edu/cgi-bin/das/"+self.hg_version+
                               "/dna?segment="+seq_range)
        req.raise_for_status()
        url = bs4.BeautifulSoup(req.text, features="xml").prettify()
        search = re.findall(r"[tacg{5}].*",url)
        
        # filters for elements which only contain nucleotides and concatenate
        seqs = [s for s in search if not s.strip("tacg")] 
        seq = "".join(seqs)
        if not seq:
            raise ErrorUCSC
        
        # split up scrapped sequence and make var upper
        downstream = seq[:self.upstream]
        var = seq[self.upstream]
        upstream = seq[self.upstream+1:len(seq)]
        answer = "".join((downstream.lower(),var.upper(),upstream.lower()))
        
        return answer
    
    
    def header_option(self,seq_name,var_pos,seq_range,sequence):
        ''' determine whether to place a header
            above the returned sequence, based 
            upon options selected by user
        '''
        # concatenate the name and outputs from Class, determine whether to 
        # add a header
        if self.header:
            header = " ".join((">",seq_name,var_pos,seq_range))
        else:
            header = ""

        # output sequences to the screen and append to a list
        return(header)




class ProteinRNA(object):
    def __init__(self, transcribe, translate, rc):
        self.transcribe = transcribe
        self.translate = translate
        self.rc = rc


    def get_rna_seq(self,sequence):
        ''' determine whether to transcribe rna,
            based upon options selected
        '''
        # perorm transcription, reverse complement and/or translation depending
        # on which options have been selected
        if self.transcribe:
         
            if self.rc:
                rna = transcription(sequence.replace("-",""),"rc")
                return rna

            else:
                rna = transcription(sequence.replace("-",""))
                return rna
        else:
            # DNA
            return sequence

    def get_protein_seq(self,rna):
        ''' determine whether to translate protein,
            based upon options selected
        '''
        if self.translate:
            protein = translation(rna)
            return protein
        else:
            return rna
   


class CompareSeqs(object):
    def __init__(self, upstream, downstream, seq_file):
        self.seq_file = seq_file
        self.upstream = upstream
        self.downstream = downstream
    
    UIPAC = {"A":"A", "C":"C", "G":"G", "T":"T",
             "R":"A/G", "Y":"C/T", "S":"G/C",
             "W":"A/T", "K":"G/T", "M":"A/C",
             "B":"C/G/T", "D":"A/G/T", "H":"A/C/T",
             "V":"A/C/G", "N":"N"}

    @staticmethod
    def get_matching_seq_file(query, directory):
        ''' find a file name that best matches given query
        '''
        # appending is required in case there is more than one match, returns first match
        store_matches = []
        for f in os.listdir(directory):
            if query in f:
                file_match = directory+f
                store_matches.append(file_match)
                
        if store_matches:
            sorted_matches = sorted(store_matches)
            return sorted_matches[0]

    def match_with_seq_file(self,sequence):
        ''' search for the sequence output from 
            get_region_info() in a given 
            .seq file and output it

            returns a tuple containing the sanger
            sequence and the var_pos nucelotide

            # NEEDS MUCH MORE TESTING
        '''
        if self.seq_file:
            # get the sequence preceding the var_pos (preseq) and the var_pos sequence (ref_seq) 
            # from the returned get_region_info() value 
            preseq = sequence[:self.upstream].upper()
            ref_seq = sequence[self.upstream].upper()
            seq_file = open(self.seq_file, "r").read()
            seq_file = seq_file.replace("\n","")
            
            # find the preseq in the seq_file string and output the indexes where the match occurred within the 
            # seq_file as a tuple
            if re.search(preseq, seq_file):
                find = [(m.start(0), m.end(0)) for m in re.finditer(preseq, seq_file)][0]
                start = find[0]
                end = find[1]
                
                # get the full sequence of interest from the seq_file
                matched_seq = seq_file[start:end]
                var_pos_seq = CompareSeqs.UIPAC.get(seq_file[end])  # convert the UIPAC to bases
                downstream_seq = seq_file[end+1:end+self.downstream+1]
                full_seq = "".join((matched_seq.lower(),var_pos_seq.upper(),
                                     downstream_seq.lower()))
                return(full_seq,ref_seq,var_pos_seq.upper())
            
            else:
                pass
        else:
            pass


    @staticmethod
    def compare_nucleotides(base_1, base_2):
            '''compare two nucleotides
            '''
            
            # assess whether a variant is present in the sanger sequence in the given proposed variant position
            if base_1 != base_2:
                return("the nucleotides given are DIFFERENT",2)

            elif base_1== base_2:
                return("the nucleotides given are the SAME",1)
            
            else:
                return "not found"


    
             
                
if __name__ == '__main__':
    main()         

# main("in.txt","b", 2, 20,"hg19","\t","y")
